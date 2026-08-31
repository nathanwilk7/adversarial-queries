SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((title CROSS JOIN name) CROSS JOIN link_type) CROSS JOIN cast_info) CROSS JOIN movie_companies) CROSS JOIN aka_title) CROSS JOIN company_type) CROSS JOIN kind_type) CROSS JOIN movie_link
WHERE aka_title.production_year > 1960
  AND name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
