SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_companies CROSS JOIN ((title CROSS JOIN complete_cast) CROSS JOIN movie_link)) CROSS JOIN kind_type) CROSS JOIN company_name) CROSS JOIN movie_keyword) CROSS JOIN link_type) CROSS JOIN movie_info) CROSS JOIN keyword) CROSS JOIN info_type
WHERE company_name.name = 'Sony Pictures Releasing'
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
