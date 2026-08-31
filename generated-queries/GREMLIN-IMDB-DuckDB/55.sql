SELECT count(*)
FROM aka_name, cast_info, company_name, keyword, kind_type, movie_companies, movie_keyword, movie_link, name, title
WHERE company_name.country_code = '[us]'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
