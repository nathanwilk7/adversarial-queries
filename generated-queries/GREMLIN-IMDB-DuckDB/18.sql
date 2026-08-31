SELECT count(*)
FROM aka_name, cast_info, company_name, link_type, movie_companies, movie_link, name, person_info, title
WHERE cast_info.nr_order > 7
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
